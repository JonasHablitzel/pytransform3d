import numpy as np
from bs4 import BeautifulSoup
from .transform_manager import TransformManager
from .transformations import transform_from, concat
from .rotations import matrix_from_euler_xyz, matrix_from_axis_angle


class UrdfTransformManager(TransformManager):
    """Transformation manager that can load URDF files.

    URDF is the `Unified Robot Description Format <http://wiki.ros.org/urdf>`_.
    URDF allows to define joints between links that can be rotated about one
    axis. This transformation manager allows to set the joint angles after
    joints have been added or loaded from an URDF.

    .. warning::

        Note that this module requires the Python package beautifulsoup4.
    """
    def __init__(self):
        super(UrdfTransformManager, self).__init__()
        self._joints = {}

    def add_joint(self, joint_name, from_frame, to_frame, child2parent, axis):
        """Add joint.

        Parameters
        ----------
        joint_name : string
            Name of the joint

        from_frame : string
            Child link of the joint

        to_frame : string
            Parent link of the joint

        child2parent : array-like, shape (4, 4)
            Transformation from child to parent

        axis : array-like, shape (3,)
            Rotation axis of the joint (defined in the child frame)
        """
        self.add_transform(from_frame, to_frame, child2parent)
        self._joints[joint_name] = from_frame, to_frame, child2parent, axis

    def set_joint(self, joint_name, angle):
        """Set joint angle.

        Parameters
        ----------
        joint_name : string
            Name of the joint

        angle : float
            Joint angle in radians
        """
        if joint_name not in self._joints:
            raise KeyError("Joint '%s' is not known" % joint_name)
        from_frame, to_frame, child2parent, axis = self._joints[joint_name]
        joint_rotation = matrix_from_axis_angle(np.hstack((axis, [angle])))
        joint2A = transform_from(joint_rotation, np.zeros(3))
        self.add_transform(from_frame, to_frame, concat(joint2A, child2parent))


    def load_urdf(self, urdf_xml):
        """Load URDF file into transformation manager.

        Parameters
        ----------
        urdf_xml : string
            Robot definition in URDF
        """
        urdf = BeautifulSoup(urdf_xml, "xml")

        robot = urdf.find("robot")
        if robot is None:
            raise UrdfException("Robot tag is missing.")

        if not robot.has_attr("name"):
            raise UrdfException("Attribute 'name' is missing in robot tag.")

        robot_name = robot["name"]

        nodes = {}
        for link in robot.findAll("link"):
            node = self._parse_link(link, robot_name)
            nodes[node.child] = node

        for joint in robot.findAll("joint"):
            if not joint.has_attr("name"):
                raise UrdfException("Joint name is missing.")
            joint_name = joint["name"]

            if not joint.has_attr("type"):
                raise UrdfException("Joint type is missing in joint '%s'."
                                    % joint_name)

            parent = joint.find("parent")
            if parent is None:
                raise UrdfException("No parent specified in joint '%s'"
                                    % joint_name)
            if not parent.has_attr("link"):
                raise UrdfException("No parent link name given in joint '%s'."
                                    % joint_name)
            parent_name = parent["link"]
            if parent_name not in nodes:
                raise UrdfException("Parent link '%s' of joint '%s' is not "
                                    "defined." % (parent_name, joint_name))

            child = joint.find("child")
            if child is None:
                raise UrdfException("No child specified in joint '%s'"
                                    % joint_name)
            if not child.has_attr("link"):
                raise UrdfException("No child link name given in joint '%s'."
                                    % joint_name)
            child_name = child["link"]
            if child_name not in nodes:
                raise UrdfException("Child link '%s' of joint '%s' is not "
                                    "defined." % (child_name, joint_name))

            self._parse_joint(joint, nodes[child_name], parent_name)

        for node in nodes.values():
            if node.joint_type == "revolute":
                self.add_joint(node.joint_name, node.child, node.parent,
                               node.child2parent, node.joint_axis)
            else:
                self.add_transform(node.child, node.parent, node.child2parent)


    def _parse_link(self, link, robot_name):
        """Make node from link."""
        if not link.has_attr("name"):
            raise UrdfException("Link name is missing.")
        return Node(link["name"], robot_name)


    def _parse_joint(self, joint, node, parent_name):
        """Update node with joint."""
        node.joint_name = joint["name"]
        node.joint_type = joint["type"]
        node.parent = parent_name

        if node.joint_type in ["planar", "floating", "continuous",
                               "prismatic"]:
            raise UrdfException("Unsupported joint type '%s'"
                                % node.joint_type)
        elif node.joint_type not in ["revolute", "fixed"]:
            raise UrdfException("Joint type '%s' is not allowed in a URDF "
                                "document." % node.joint_type)

        origin = joint.find("origin")
        translation = np.zeros(3)
        rotation = np.eye(3)
        if origin is not None:
            if origin.has_attr("xyz"):
                translation = np.fromstring(origin["xyz"], sep=" ")
            if origin.has_attr("rpy"):
                roll_pitch_yaw = np.fromstring(origin["rpy"], sep=" ")
                # URDF and KDL use the alias convention for rotation matrices
                # instead of alibi convention. That means the reference frame
                # is rotated by the rotation matrix and not the point. To
                # convert the defined rotation to the alibi convention we must
                # invert (transpose) the matrix.
                # For more details on how the URDF parser handles the
                # conversion from Euler angles, see this blog post:
                # https://orbitalstation.wordpress.com/tag/quaternion/
                rotation = matrix_from_euler_xyz(roll_pitch_yaw).T
        node.child2parent = transform_from(rotation, translation)

        node.joint_axis = np.array([1, 0, 0])
        if node.joint_type == "revolute":
            axis = joint.find("axis")
            if axis is not None and axis.has_attr("xyz"):
                node.joint_axis = np.fromstring(axis["xyz"], sep=" ")


class Node(object):
    """Node from URDF file.

    This class is only required temporarily while we parse the URDF.

    Parameters
    ----------
    child : string
        Name of the child

    parent : string
        Name of the parent frame

    Attributes
    ----------
    child : string
        Name of the child

    parent : string
        Name of the parent frame

    child2parent : array-like, shape (4, 4)
        Transformation from child to parent

    joint_name : string
        Name of the joint that defines the transformation

    joint_axis : array-like, shape (3,)
        Rotation axis of the joint (defined in the child frame)

    joint_type : string
        Either 'fixed' or 'revolute'
    """
    def __init__(self, child, parent):
        self.child = child
        self.parent = parent
        self.child2parent = np.eye(4)
        self.joint_name = None
        self.joint_axis = None
        self.joint_type = "fixed"


class UrdfException(Exception):
    """Exception while parsing URDF files."""
    pass
